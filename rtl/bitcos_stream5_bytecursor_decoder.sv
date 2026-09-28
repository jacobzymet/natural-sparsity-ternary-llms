// Five-position BITCOS streaming decoder with a byte-granular cursor.
//
// A 16-bit {next,current} sign window is sufficient because the largest
// requested slice starts at offset 7 and spans five bits, ending at bit 11.
// At most one sign-byte boundary can therefore be crossed per cycle.
module bitcos_stream5_bytecursor_decoder (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       start_block,
    input  logic [2:0] initial_offset,
    input  logic       advance,
    input  logic [7:0] current_sign_byte,
    input  logic [7:0] next_sign_byte,
    input  logic [4:0] presence,
    output logic [9:0] weights_2b,
    output logic [2:0] consumed_signs,
    output logic [2:0] offset_state,
    output logic       advance_sign_byte
);
    logic [2:0] offset;
    logic [15:0] sign_pair;
    logic [15:0] shifted_pair;
    logic [4:0] sign_window;
    logic [3:0] offset_plus_consumed;

    assign sign_pair = {next_sign_byte, current_sign_byte};
    assign shifted_pair = sign_pair >> offset;
    assign sign_window = shifted_pair[4:0];

    bitcos_group5_decode decode (
        .presence(presence),
        .sign_window(sign_window),
        .weights_2b(weights_2b),
        .consumed_signs(consumed_signs)
    );

    always_comb begin
        offset_plus_consumed = {1'b0, offset} + consumed_signs;
        advance_sign_byte = advance && offset_plus_consumed[3];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            offset <= '0;
        else if (start_block)
            offset <= initial_offset;
        else if (advance)
            offset <= offset_plus_consumed[2:0];
    end

    assign offset_state = offset;
endmodule
